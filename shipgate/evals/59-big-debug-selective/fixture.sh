#!/usr/bin/env bash
# Scaffold: builds the bigshop monorepo (fixtures/bigshop.py, embedded) in the CURRENT directory, which is the repo root.
set -e
python3 - --variant selective <<'PYGEN'
"""bigshop — a deterministic ~180-file, 60-commit, journaled monorepo fixture.

Usage (from an empty directory, which becomes the repo root):
    python3 bigshop.py --variant <case>

The repo is written into the CURRENT directory (not app/), so the agent's cwd is the project
root: the plugin's hooks find `.claude/shipgate.json` by walking ancestors of cwd, and the
skills read `.claude/shipgate.md` from the project root exactly as on a real project.

Variants plant one scenario each on top of the shared history (see VARIANTS). Everything is
synthetic; nothing here refers to a real project.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import textwrap

GIT_ENV_BASE = {"GIT_AUTHOR_NAME": "dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
                "GIT_COMMITTER_NAME": "dev", "GIT_COMMITTER_EMAIL": "dev@example.com"}


def sh(*args, **kw):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


def write(path, body):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(textwrap.dedent(body).lstrip("\n"))


def append(path, text):
    with open(path, "a") as fh:
        fh.write(text)


def replace(path, old, new):
    s = open(path).read()
    assert old in s, f"{path}: pattern not found: {old[:60]}"
    open(path, "w").write(s.replace(old, new, 1))


def commit(day, msg):
    ts = f"{day}T10:00:00+00:00"
    env = dict(os.environ, **GIT_ENV_BASE, GIT_AUTHOR_DATE=ts, GIT_COMMITTER_DATE=ts)
    sh("git", "add", "-A")
    sh("git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-q", "--allow-empty", "-m", msg, env=env)


# ----------------------------------------------------------------------------- shared/
def write_shared():
    write("shared/__init__.py", "")
    write("shared/dates.py", '''
        """Payment-terms dates shared by api and worker."""
        from datetime import timedelta


        def due_date(issued, net_days):
            """Issued + net days; a due date on a weekend moves to the following Monday."""
            d = issued + timedelta(days=net_days)
            while d.weekday() >= 5:
                d += timedelta(days=1)
            return d


        def days_until_due(issued, net_days, today):
            """Whole days from `today` to the due date; negative once past."""
            return (due_date(issued, net_days) - today).days


        def is_overdue(issued, net_days, today, grace_days=3):
            return today > due_date(issued, net_days) + timedelta(days=grace_days)
    ''')
    write("shared/money.py", '''
        from decimal import Decimal, ROUND_HALF_UP

        CENT = Decimal("0.01")


        def fmt(cents):
            sign = "-" if cents < 0 else ""
            cents = abs(cents)
            return f"{sign}{cents // 100}.{cents % 100:02d}"


        def quantize(amount):
            return amount.quantize(CENT, rounding=ROUND_HALF_UP)
    ''')
    write("shared/vat.py", '''
        from decimal import Decimal

        RATES = {"DE": Decimal("0.19"), "FR": Decimal("0.20"), "NL": Decimal("0.21"), "US": Decimal("0")}


        def to_gross(net, country):
            return net * (1 + RATES[country])


        def to_net(gross, country):
            return gross / (1 + RATES[country])
    ''')
    write("shared/events.py", '''
        """In-process event bus; the worker consumes what api emits."""
        from collections import defaultdict


        class Bus:
            def __init__(self):
                self.handlers = defaultdict(list)
                self.log = []

            def on(self, event_type, handler):
                self.handlers[event_type].append(handler)

            def emit(self, event_type, **data):
                self.log.append((event_type, data))
                for h in self.handlers[event_type]:
                    h(data)

            def pending(self, event_type):
                return [d for t, d in self.log if t == event_type]
    ''')
    for name, body in {
        "ids.py": "import itertools\n\n_counter = itertools.count(1000)\n\n\ndef next_id(prefix):\n    return f\"{prefix}-{next(_counter)}\"\n",
        "validation.py": "def require(cond, message):\n    if not cond:\n        raise ValueError(message)\n\n\ndef non_negative(value, name):\n    require(value >= 0, f\"{name} must be >= 0\")\n    return value\n",
        "config.py": "import os\n\n\ndef env(name, default=None):\n    return os.environ.get(name, default)\n",
        "logging_.py": "import logging\n\nlog = logging.getLogger(\"shop\")\n",
        "retry.py": "def retry(fn, attempts=3):\n    last = None\n    for _ in range(attempts):\n        try:\n            return fn()\n        except Exception as exc:  # noqa: BLE001\n            last = exc\n    raise last\n",
        "clock.py": "from datetime import date, datetime, timezone\n\n\ndef today():\n    return date.today()\n\n\ndef now():\n    return datetime.now(timezone.utc)\n",
        "text.py": "def slug(value):\n    return \"-\".join(value.lower().split())\n\n\ndef truncate(value, n=40):\n    return value if len(value) <= n else value[: n - 1] + \"…\"\n",
        "pagination.py": "def paginate(items, page, size):\n    if size <= 0 or page < 1:\n        raise ValueError(\"bad page or size\")\n    start = (page - 1) * size\n    return items[start:start + size]\n",
        "csvio.py": "import csv\nimport io\n\n\ndef to_csv(header, rows):\n    buf = io.StringIO()\n    w = csv.writer(buf, lineterminator=\"\\n\")\n    w.writerow(header)\n    w.writerows(rows)\n    return buf.getvalue()\n",
        "errors.py": "class ShopError(Exception):\n    pass\n\n\nclass NotFound(ShopError):\n    pass\n\n\nclass Conflict(ShopError):\n    pass\n",
    }.items():
        write(f"shared/{name}", body)
    write("shared/tests/__init__.py", "")
    write("shared/tests/test_dates.py", '''
        import unittest
        from datetime import date

        from shared.dates import days_until_due, due_date, is_overdue


        class DatesTest(unittest.TestCase):
            def test_weekend_rolls_forward(self):
                self.assertEqual(due_date(date(2026, 9, 4), 1), date(2026, 9, 7))

            def test_days_until_due(self):
                self.assertEqual(days_until_due(date(2026, 9, 1), 30, date(2026, 9, 21)), 10)

            def test_overdue_after_grace(self):
                self.assertTrue(is_overdue(date(2026, 9, 1), 30, date(2026, 10, 5)))
    ''')
    write("shared/tests/test_money.py", '''
        import unittest

        from shared.money import fmt


        class MoneyTest(unittest.TestCase):
            def test_fmt(self):
                self.assertEqual(fmt(11900), "119.00")
                self.assertEqual(fmt(-150), "-1.50")
    ''')


# ----------------------------------------------------------------------------- services/api
API_CLAUDE = '''
    # services/api

    - Endpoints are registered in `routes.py`; handlers live in `handlers/` next to their domain module.
    - Read-only reporting endpoints (aggregates, exports, dashboards) go under `reports/`, never in
      `routes.py` — they are mounted separately so they can be rate-limited and cached as a group.
    - Order state changes (placed, shipped, cancelled) happen only here, in `orders.py`.
    - SQL is always parameterised (`db.query(sql, *params)`); never interpolate values into SQL.
    - Money is formatted only through `shared.money.fmt`.
    - Tests: `python3 -m unittest discover -s services/api/tests -t .` from the repo root.
'''


def write_api():
    write("services/api/CLAUDE.md", API_CLAUDE)
    write("services/api/__init__.py", "")
    write("services/api/config.py", "PAGE_SIZE = 20\nDATABASE_URL = \"sqlite:///shop.db\"\nEXPORT_MAX_ROWS = 50000\n")
    write("services/api/db.py", '''
        """Thin query layer over sqlite (production runs the migrations in migrations/)."""
        import sqlite3


        class DB:
            def __init__(self, path=":memory:"):
                self.conn = sqlite3.connect(path)
                self.conn.execute("PRAGMA foreign_keys=ON")

            def query(self, sql, *params):
                return self.conn.execute(sql, params).fetchall()

            def execute(self, sql, *params):
                cur = self.conn.execute(sql, params)
                self.conn.commit()
                return cur.lastrowid
    ''')
    write("services/api/flags.py", "FLAGS = {\n    \"orders-bulk-cancel\": False,\n    \"export-async\": False,\n}\n")
    write("services/api/customers.py", '''
        from shared.errors import NotFound


        def get_customer(db, customer_id):
            rows = db.query("SELECT id, name, email, country, prices_include_vat FROM customers WHERE id = ?", customer_id)
            if not rows:
                raise NotFound(f"customer {customer_id}")
            return rows[0]


        def list_customers(db, limit=20):
            return db.query("SELECT id, name, email, country, prices_include_vat FROM customers ORDER BY id LIMIT ?", limit)
    ''')
    write("services/api/invoices.py", '''
        from decimal import Decimal

        from shared.money import quantize
        from shared.vat import to_gross


        def line_amount(item, customer):
            price = Decimal(item["price"])
            return price * item["qty"]


        def invoice_total(items, customer):
            net = sum((line_amount(i, customer) for i in items), Decimal(0))
            return quantize(to_gross(net, customer["country"]))


        def list_invoices(db, status=None, limit=20):
            if status:
                return db.query("SELECT number, customer_id, total, status, issued FROM invoices WHERE status = ? ORDER BY issued LIMIT ?", status, limit)
            return db.query("SELECT number, customer_id, total, status, issued FROM invoices ORDER BY issued LIMIT ?", limit)
    ''')
    write("services/api/pricing.py", '''
        """Order pricing: subtotal, percentage discounts, rounding."""
        from decimal import Decimal, ROUND_HALF_UP

        CENT = Decimal("0.01")


        def line_total(unit_price, qty):
            return Decimal(str(unit_price)) * qty


        def apply_discount(amount, percent):
            discounted = amount * (Decimal(100) - Decimal(str(percent))) / Decimal(100)
            return discounted.quantize(CENT, rounding=ROUND_HALF_UP)


        def order_total(lines, discount_percent=0):
            subtotal = sum((line_total(p, q) for p, q in lines), Decimal(0))
            return apply_discount(subtotal, discount_percent)
    ''')
    write("services/api/terms.py", '''
        """Thin wrapper so api code never imports the shared helpers by path."""
        from shared.dates import days_until_due, due_date, is_overdue  # noqa: F401
    ''')
    write("services/api/orders.py", '''
        """Order state machine — the only place order rows change."""
        from shared.errors import Conflict

        STATES = ("placed", "shipped", "cancelled")


        def place_order(db, bus, customer_id, items):
            order_id = db.execute("INSERT INTO orders (customer_id, status) VALUES (?, 'placed')", customer_id)
            for item in items:
                db.execute("INSERT INTO order_items (order_id, sku, qty) VALUES (?, ?, ?)", order_id, item["sku"], item["qty"])
            bus.emit("order.placed", order_id=order_id)
            return order_id


        def apply_shipped(db, bus, order_id, carrier_ref):
            """Applied when the worker emits order.shipped."""
            row = db.query("SELECT status FROM orders WHERE id = ?", order_id)
            if not row or row[0][0] != "placed":
                raise Conflict(f"order {order_id} is not placed")
            db.execute("UPDATE orders SET status = 'shipped', carrier_ref = ? WHERE id = ?", carrier_ref, order_id)
            bus.emit("notify.order_shipped", order_id=order_id)
    ''')
    write("services/api/payments.py", '''
        def record_payment(db, bus, invoice_number, amount_cents, received):
            pid = db.execute("INSERT INTO payments (invoice_number, amount, received) VALUES (?, ?, ?)", invoice_number, amount_cents, received)
            bus.emit("payment.recorded", payment_id=pid, invoice_number=invoice_number)
            return pid


        def payments_for(db, customer_id):
            return db.query("SELECT p.invoice_number, p.amount, p.received FROM payments p JOIN invoices i ON i.number = p.invoice_number WHERE i.customer_id = ?", customer_id)
    ''')
    write("services/api/export.py", '''
        """Invoice CSV export (PRD #401)."""
        from shared.csvio import to_csv
        from shared.money import fmt

        HEADER = ("number", "customer", "total", "status")


        def export_rows(records):
            return [(number, customer, fmt(total), status) for number, customer, total, status in records]


        def export(db, status=None):
            if status:
                records = db.query("SELECT i.number, c.name, i.total, i.status FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.status = ?", status)
            else:
                records = db.query("SELECT i.number, c.name, i.total, i.status FROM invoices i JOIN customers c ON c.id = i.customer_id")
            return to_csv(HEADER, export_rows(records))
    ''')
    write("services/api/statements.py", '''
        """Monthly statements — balances computed from invoices and payments (PRD #440, design pending)."""


        def opening_balance(db, customer_id, month_start):
            inv = db.query("SELECT COALESCE(SUM(total), 0) FROM invoices WHERE customer_id = ? AND issued < ?", customer_id, month_start)[0][0]
            paid = db.query("SELECT COALESCE(SUM(p.amount), 0) FROM payments p JOIN invoices i ON i.number = p.invoice_number WHERE i.customer_id = ? AND p.received < ?", customer_id, month_start)[0][0]
            return inv - paid
    ''')
    write("services/api/reminders.py", '''
        """Payment reminders — not built yet (PRD #470 in clarify)."""
    ''')
    write("services/api/auth.py", "def current_user(req):\n    return req.get(\"user\")\n\n\ndef require_admin(req):\n    if not (current_user(req) or {}).get(\"admin\"):\n        raise PermissionError(\"admin only\")\n")
    write("services/api/audit.py", "def record(db, actor, action, target):\n    db.execute(\"INSERT INTO audit (actor, action, target) VALUES (?, ?, ?)\", actor, action, target)\n")
    write("services/api/routes.py", '''
        """Route table. Handlers live in handlers/; reports are mounted separately (see reports/)."""
        from services.api.handlers import customers as h_customers
        from services.api.handlers import invoices as h_invoices
        from services.api.handlers import orders as h_orders
        from services.api.handlers import payments as h_payments

        ROUTES = {}


        def route(method, path):
            def deco(fn):
                ROUTES[(method, path)] = fn
                return fn
            return deco


        route("GET", "/customers")(h_customers.list_)
        route("GET", "/customers/{id}")(h_customers.get)
        route("GET", "/invoices")(h_invoices.list_)
        route("GET", "/invoices/{number}")(h_invoices.get)
        route("POST", "/orders")(h_orders.create)
        route("POST", "/events/order.shipped")(h_orders.on_shipped)
        route("POST", "/payments")(h_payments.create)
    ''')
    write("services/api/handlers/__init__.py", "")
    for mod, body in {
        "customers": "from services.api import customers\n\n\ndef list_(req, db):\n    return [dict(zip((\"id\", \"name\", \"email\", \"country\", \"prices_include_vat\"), r)) for r in customers.list_customers(db, req.get(\"limit\", 20))]\n\n\ndef get(req, db):\n    return customers.get_customer(db, req[\"id\"])\n",
        "invoices": "from services.api import invoices\nfrom shared.money import fmt\n\n\ndef list_(req, db):\n    return [{\"number\": n, \"customer_id\": c, \"total\": fmt(t), \"status\": s, \"issued\": str(i)} for n, c, t, s, i in invoices.list_invoices(db, req.get(\"status\"), req.get(\"limit\", 20))]\n\n\ndef get(req, db):\n    rows = invoices.list_invoices(db)\n    return next((r for r in rows if r[0] == req[\"number\"]), None)\n",
        "orders": "from services.api import orders\n\n\ndef create(req, db, bus=None):\n    return {\"id\": orders.place_order(db, bus, req[\"customer_id\"], req[\"items\"])}\n\n\ndef on_shipped(req, db, bus=None):\n    orders.apply_shipped(db, bus, req[\"order_id\"], req[\"carrier_ref\"])\n    return {\"ok\": True}\n",
        "payments": "from services.api import payments\n\n\ndef create(req, db, bus=None):\n    return {\"id\": payments.record_payment(db, bus, req[\"invoice_number\"], req[\"amount\"], req[\"received\"])}\n",
        "health": "def get(req, db):\n    return {\"ok\": True}\n",
        "flags": "from services.api.flags import FLAGS\n\n\ndef get(req, db):\n    return dict(FLAGS)\n",
        "audit": "from services.api import audit\n\n\ndef record(req, db):\n    audit.record(db, req[\"actor\"], req[\"action\"], req[\"target\"])\n    return {\"ok\": True}\n",
        "statements": "from services.api import statements\n\n\ndef opening(req, db):\n    return {\"opening\": statements.opening_balance(db, req[\"customer_id\"], req[\"month_start\"])}\n",
    }.items():
        write(f"services/api/handlers/{mod}.py", body)
    write("services/api/reports/__init__.py", '"""Read-only reporting endpoints, mounted under /reports (api CLAUDE.md)."""\n')
    write("services/api/reports/customers.py", "def orders_per_customer(db, since):\n    return db.query(\"SELECT customer_id, COUNT(*) FROM orders WHERE placed_at >= ? GROUP BY customer_id\", since)\n")
    write("services/api/reports/aging.py", "def aging_buckets(db, today):\n    return db.query(\"SELECT status, COUNT(*) FROM invoices GROUP BY status\")\n")
    migrations = {
        "0001_customers.sql": "CREATE TABLE customers (\n  id INTEGER PRIMARY KEY,\n  name TEXT NOT NULL,\n  email TEXT NOT NULL,\n  country TEXT NOT NULL,\n  prices_include_vat INTEGER NOT NULL DEFAULT 0\n);\n",
        "0002_invoices.sql": "CREATE TABLE invoices (\n  number TEXT PRIMARY KEY,\n  customer_id INTEGER NOT NULL REFERENCES customers(id),\n  total INTEGER NOT NULL,\n  status TEXT NOT NULL CHECK (status IN ('open', 'paid', 'void')),\n  issued DATE NOT NULL,\n  net_days INTEGER NOT NULL DEFAULT 30\n);\n",
        "0003_orders.sql": "CREATE TABLE orders (\n  id INTEGER PRIMARY KEY,\n  customer_id INTEGER NOT NULL REFERENCES customers(id),\n  status TEXT NOT NULL,\n  placed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,\n  carrier_ref TEXT\n);\nCREATE TABLE order_items (\n  id INTEGER PRIMARY KEY,\n  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,\n  sku TEXT NOT NULL,\n  qty INTEGER NOT NULL\n);\n",
        "0004_payments.sql": "CREATE TABLE payments (\n  id INTEGER PRIMARY KEY,\n  invoice_number TEXT NOT NULL REFERENCES invoices(number),\n  amount INTEGER NOT NULL,\n  received DATE NOT NULL\n);\n",
        "0005_audit.sql": "CREATE TABLE audit (\n  id INTEGER PRIMARY KEY,\n  actor TEXT NOT NULL,\n  action TEXT NOT NULL,\n  target TEXT NOT NULL,\n  at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP\n);\n",
        "0006_invoice_net_days_index.sql": "CREATE INDEX idx_invoices_status_issued ON invoices(status, issued);\n",
        "0007_notification_log.sql": "CREATE TABLE notification_log (\n  id INTEGER PRIMARY KEY,\n  event_type TEXT NOT NULL,\n  recipient TEXT NOT NULL,\n  sent_at TIMESTAMP NOT NULL,\n  status TEXT NOT NULL\n);\n",
        "0008_customers_vat_flag.sql": "-- prices_include_vat added to customers in 0001; this migration backfills EU rows\nUPDATE customers SET prices_include_vat = 1 WHERE country IN ('DE', 'FR', 'NL');\n",
    }
    for name, body in migrations.items():
        write(f"services/api/migrations/{name}", body)
    write("services/api/tests/__init__.py", "")
    write("services/api/tests/_fixtures.py", '''
        from services.api.db import DB


        def seeded():
            db = DB()
            for sql in open_migrations():
                db.conn.executescript(sql)
            db.execute("INSERT INTO customers (id, name, email, country, prices_include_vat) VALUES (1, 'Acme', 'ap@acme.example', 'US', 0)")
            db.execute("INSERT INTO customers (id, name, email, country, prices_include_vat) VALUES (2, 'Globex, Inc.', 'ap@globex.example', 'DE', 1)")
            db.execute("INSERT INTO invoices (number, customer_id, total, status, issued) VALUES ('INV-001', 1, 20000, 'open', '2026-09-01')")
            db.execute("INSERT INTO invoices (number, customer_id, total, status, issued) VALUES ('INV-002', 2, 11900, 'paid', '2026-08-20')")
            return db


        def open_migrations():
            import glob
            import os
            here = os.path.join(os.path.dirname(__file__), "..", "migrations")
            return [open(p).read() for p in sorted(glob.glob(os.path.join(here, "*.sql"))) if "0008" not in p]
    ''')
    write("services/api/tests/test_pricing.py", '''
        import unittest
        from decimal import Decimal

        from services.api.pricing import order_total


        class PricingTest(unittest.TestCase):
            def test_discount(self):
                self.assertEqual(order_total([(19.99, 3)], 15), Decimal("50.97"))

            def test_no_discount(self):
                self.assertEqual(order_total([(10, 1)]), Decimal("10.00"))

            def test_fractional_unit_price(self):
                self.assertEqual(order_total([(0.333, 3)]), Decimal("1.00"))
    ''')
    write("services/api/tests/test_invoices.py", '''
        import unittest
        from decimal import Decimal

        from services.api.invoices import invoice_total

        US = {"country": "US", "prices_include_vat": 0}


        class InvoiceTotalTest(unittest.TestCase):
            def test_us_customer(self):
                self.assertEqual(invoice_total([{"price": "100.00", "qty": 2}], US), Decimal("200.00"))
    ''')
    write("services/api/tests/test_export.py", '''
        import csv
        import io
        import unittest

        from services.api.export import export
        from services.api.tests._fixtures import seeded


        class ExportTest(unittest.TestCase):
            def test_header_and_quoting(self):
                rows = list(csv.reader(io.StringIO(export(seeded()))))
                self.assertEqual(rows[0], ["number", "customer", "total", "status"])
                self.assertTrue(all(len(r) == 4 for r in rows))
    ''')
    write("services/api/tests/test_orders.py", '''
        import unittest

        from services.api.orders import apply_shipped, place_order
        from services.api.tests._fixtures import seeded
        from shared.events import Bus


        class OrdersTest(unittest.TestCase):
            def test_place_and_ship(self):
                db, bus = seeded(), Bus()
                oid = place_order(db, bus, 1, [{"sku": "A", "qty": 1}])
                apply_shipped(db, bus, oid, "CARRIER-1")
                self.assertEqual(db.query("SELECT status FROM orders WHERE id = ?", oid)[0][0], "shipped")
                self.assertEqual([t for t, _ in bus.log], ["order.placed", "notify.order_shipped"])
    ''')
    for n in ("customers", "payments", "statements", "routes", "handlers", "audit"):
        write(f"services/api/tests/test_{n}.py", f'''
            import unittest


            class {n.title()}Test(unittest.TestCase):
                def test_module_imports(self):
                    import services.api.{n if n != "handlers" else "handlers.customers"}  # noqa: F401
        ''')


# ----------------------------------------------------------------------------- services/worker
WORKER_CLAUDE = '''
    # services/worker

    - The worker never writes to the order or invoice tables. It consumes `order.*` / `payment.*`
      events, does the slow work (carrier booking, notifications, recomputation) and emits result
      events that `services/api` applies. Anything that mutates orders belongs in `services/api`.
    - Scheduled jobs are registered in `schedule.py`; one module per job under `jobs/`.
    - The schema the worker reads is `schema_snapshot.sql` — regenerated from api's migrations by
      `make snapshot`, never edited by hand.
    - Tests: `python3 -m unittest discover -s services/worker/tests -t .` from the repo root.
'''


def write_worker():
    write("services/worker/CLAUDE.md", WORKER_CLAUDE)
    write("services/worker/__init__.py", "")
    write("services/worker/schedule.py", '''
        from services.worker.jobs import retry_failed_notifications, snapshot_check, stale_orders

        SCHEDULE = {
            "*/15 * * * *": retry_failed_notifications.run,   # fixed interval, max 3 (ADR 0007)
            "0 6 * * *": stale_orders.run,
            "0 7 * * *": snapshot_check.run,
        }
    ''')
    write("services/worker/notifications.py", '''
        """Delivers notify.* events (ADR 0003). api never sends; it enqueues."""
        TEMPLATES = {
            "notify.order_shipped": "Your order {order_id} has shipped.",
            "notify.payment_received": "We received your payment for {invoice_number}.",
        }


        def on_notify(mailer, event):
            template = TEMPLATES[event["type"]]
            mailer.send(event["recipient"], template.format(**event))
    ''')
    write("services/worker/shipping.py", '''
        """Consumes order.placed, books the carrier, emits order.shipped."""


        def on_order_placed(bus, carrier, order_id):
            ref = carrier.book(order_id)
            bus.emit("order.shipped", order_id=order_id, carrier_ref=ref)
    ''')
    write("services/worker/jobs/__init__.py", "")
    jobs = {
        "retry_failed_notifications": "def run(bus):\n    for ev in bus.pending(\"notify.failed\")[:50]:\n        if ev.get(\"attempt\", 0) < 3:\n            bus.emit(\"notify.retry\", **{**ev, \"attempt\": ev.get(\"attempt\", 0) + 1})\n        else:\n            bus.emit(\"notify.dead\", **ev)\n",
        "stale_orders": "def run(bus, db=None):\n    # reads only; emits order.stale for api to act on\n    for oid in (db.query(\"SELECT id FROM orders WHERE status = 'placed' AND placed_at < date('now', '-14 day')\") if db else []):\n        bus.emit(\"order.stale\", order_id=oid[0])\n",
        "snapshot_check": "import hashlib\n\n\ndef run(bus, snapshot_path=\"services/worker/schema_snapshot.sql\"):\n    digest = hashlib.sha256(open(snapshot_path, \"rb\").read()).hexdigest()\n    bus.emit(\"worker.snapshot_checked\", digest=digest)\n",
        "carrier_sync": "def run(bus, carrier):\n    for ref, status in carrier.updates():\n        bus.emit(\"carrier.update\", carrier_ref=ref, status=status)\n",
        "payment_matcher": "def run(bus, db=None):\n    for p in (db.query(\"SELECT id, invoice_number FROM payments WHERE matched = 0\") if db else []):\n        bus.emit(\"payment.matched\", payment_id=p[0], invoice_number=p[1])\n",
        "digest_placeholder": "\"\"\"Reserved for the overdue digest (PRD #462, not designed yet).\"\"\"\n",
        "metrics": "def run(bus):\n    bus.emit(\"worker.heartbeat\")\n",
        "cleanup": "def run(bus, db=None):\n    bus.emit(\"worker.cleanup\")\n",
    }
    for name, body in jobs.items():
        write(f"services/worker/jobs/{name}.py", body)
    write("services/worker/schema_snapshot.sql", "-- generated by `make snapshot`; do not edit\n")
    write("services/worker/tests/__init__.py", "")
    write("services/worker/tests/test_retry.py", '''
        import unittest

        from services.worker.jobs import retry_failed_notifications
        from shared.events import Bus


        class RetryTest(unittest.TestCase):
            def test_dead_after_three(self):
                bus = Bus()
                bus.emit("notify.failed", recipient="a@example.com", type="notify.order_shipped", order_id=1, attempt=3)
                retry_failed_notifications.run(bus)
                self.assertTrue(any(t == "notify.dead" for t, _ in bus.log))
    ''')
    for n in ("shipping", "notifications", "schedule", "snapshot_check"):
        write(f"services/worker/tests/test_{n}.py", f'''
            import unittest


            class {n.title()}Test(unittest.TestCase):
                def test_module_imports(self):
                    import services.worker.{n if n != "snapshot_check" else "jobs.snapshot_check"}  # noqa: F401
        ''')


# ----------------------------------------------------------------------------- web/
WEB_CLAUDE = '''
    # web

    - Components live in `src/components/`; pages in `src/pages/`; the order list is `src/components/OrderList.js`.
    - Money is formatted only through `src/money.js`; never format money inside a component.
    - Feature flags come from `src/flags.js`; the API client is `src/api.js` — components never fetch directly.
    - The web app never talks to the worker.
'''


def write_web():
    write("web/CLAUDE.md", WEB_CLAUDE)
    write("web/package.json", "{\n  \"name\": \"shop-web\",\n  \"version\": \"1.0.0\",\n  \"private\": true\n}\n")
    write("web/src/money.js", "export const formatMoney = (cents) => `${cents < 0 ? '-' : ''}${Math.floor(Math.abs(cents) / 100)}.${String(Math.abs(cents) % 100).padStart(2, '0')}`;\n")
    write("web/src/flags.js", "export const FLAGS = { 'orders-bulk-cancel': false, 'export-async': false };\n")
    write("web/src/api.js", "export async function get(path) {\n  const res = await fetch(`/api${path}`);\n  if (!res.ok) throw new Error(`GET ${path}: ${res.status}`);\n  return res.json();\n}\n\nexport async function post(path, body) {\n  const res = await fetch(`/api${path}`, { method: 'POST', body: JSON.stringify(body) });\n  return res.json();\n}\n")
    write("web/src/router.js", "import { pages } from './pages/index.js';\n\nexport function route(path) {\n  return pages[path] || pages['/'];\n}\n")
    write("web/src/store.js", "const state = { customers: [], invoices: [], orders: [] };\nexport const store = {\n  get: (k) => state[k],\n  set: (k, v) => { state[k] = v; },\n};\n")
    components = ["OrderList", "OrderRow", "InvoiceList", "InvoiceRow", "CustomerCard", "CustomerPicker", "StatusBadge", "Pagination", "DateRange", "SearchBox",
                  "Toast", "Modal", "Button", "Table", "EmptyState", "Spinner", "ErrorBanner", "FlagGate", "MoneyCell", "Header",
                  "Footer", "Sidebar", "Breadcrumbs", "Tabs", "Tooltip", "Dropdown", "Checkbox", "Form", "Field", "Avatar"]
    for c in components:
        imports = "import { formatMoney } from '../money.js';\n" if c in ("OrderList", "InvoiceList", "MoneyCell", "OrderRow", "InvoiceRow") else ""
        imports += "import { FLAGS } from '../flags.js';\n" if c in ("FlagGate", "OrderList") else ""
        body = f"{imports}\nexport function {c}(props = {{}}) {{\n  return `<div class=\"{c.lower()}\">${{props.children || ''}}</div>`;\n}}\n"
        if c == "OrderList":
            body = ("import { formatMoney } from '../money.js';\nimport { FLAGS } from '../flags.js';\nimport { StatusBadge } from './StatusBadge.js';\n\n"
                    "export function OrderList({ orders }) {\n  return orders.map((o) => `${o.id} ${StatusBadge({ status: o.status })} ${formatMoney(o.total)}`).join('\\n');\n}\n")
        write(f"web/src/components/{c}.js", body)
    pages = ["Home", "Orders", "OrderDetail", "Invoices", "InvoiceDetail", "Customers", "CustomerDetail", "Reports", "Settings", "Flags", "NotFound", "Login"]
    for p in pages:
        comp = {"Orders": "OrderList", "Invoices": "InvoiceList", "Customers": "CustomerCard"}.get(p, "Table")
        write(f"web/src/pages/{p}.js", f"import {{ {comp} }} from '../components/{comp}.js';\nimport {{ get }} from '../api.js';\n\nexport async function {p}Page() {{\n  const data = await get('/{p.lower()}');\n  return {comp}({{ children: JSON.stringify(data) }});\n}}\n")
    write("web/src/pages/index.js", "".join(f"import {{ {p}Page }} from './{p}.js';\n" for p in pages) + "\nexport const pages = {\n" + "".join(f"  '/{p.lower()}': {p}Page,\n" for p in pages) + "  '/': HomePage,\n};\n")
    for t in ("money", "OrderList", "Pagination", "api", "router"):
        write(f"web/tests/{t}.test.js", f"import assert from 'node:assert';\nimport {{ test }} from 'node:test';\n\ntest('{t} module loads', async () => {{\n  const mod = await import('../src/{'components/' if t[0].isupper() else ''}{t}.js');\n  assert.ok(mod);\n}});\n")


# ----------------------------------------------------------------------------- docs + config
ADRS = [
    ("0001-api-owns-schema", "api owns the schema", "Only `services/api` runs migrations; the worker reads a generated `schema_snapshot.sql`.", "accepted", "2026-03-10"),
    ("0002-event-bus-in-process", "In-process event bus, not a broker", "Events travel on `shared.events.Bus` within one deployment; a broker is deferred until a second deployable needs it.", "accepted", "2026-03-18"),
    ("0003-notifications-go-through-worker", "All customer notifications are sent by the worker", "Every outbound customer notification (email, SMS, push) is sent by `services/worker`; `services/api` never sends — it emits a `notify.*` event with recipient and template. A new notification = a new event emitted by api + a handler in the worker's `notifications.py`.", "accepted", "2026-04-02"),
    ("0004-money-as-integer-cents", "Money is stored as integer cents", "All amounts are integer cents in storage and events; formatting happens only in `shared.money.fmt` / `web/src/money.js`.", "accepted", "2026-04-09"),
    ("0005-reports-mounted-separately", "Reporting endpoints live under reports/", "Read-only aggregates are mounted under `/reports` from `services/api/reports/` so they can be cached and rate-limited as a group; they never go in `routes.py`.", "accepted", "2026-04-30"),
    ("0006-vat-inclusive-price-lists", "EU customers get VAT-inclusive price lists", "Customers in DE/FR/NL carry `prices_include_vat = 1`; their list prices already include VAT and must be netted before totals are computed.", "accepted", "2026-05-14"),
    ("0007-notification-retries", "Notification retries are fixed-interval, not exponential", "Failed `notify.*` deliveries are retried by `retry_failed_notifications` at a fixed 15-minute interval, at most 3 times, then marked `notify.dead`. Exponential backoff was tried in April and produced bursts against provider rate limits when many failures aligned. Changing the policy means superseding this ADR.", "accepted", "2026-06-02"),
    ("0008-cascade-deletes-via-fk", "Order items cascade through foreign keys", "`order_items` uses `ON DELETE CASCADE`; every sqlite connection sets `PRAGMA foreign_keys=ON` in `db.py` or the cascade silently does nothing.", "accepted", "2026-06-20"),
    ("0009-csv-export-synchronous", "CSV export renders synchronously", "`GET /reports/invoices.csv` renders in the request up to `EXPORT_MAX_ROWS`; an async job is deferred (flag `export-async` reserved).", "accepted", "2026-07-08"),
    ("0010-web-never-formats-money", "Web components never format money", "Supersedes nothing; records that `web/src/money.js` is the only formatter after three components drifted.", "accepted", "2026-07-22"),
    ("0011-audit-log-table", "Audit log is a table, not a file", "Admin actions are recorded in the `audit` table (migration 0005), written by api only.", "accepted", "2026-08-05"),
    ("0012-order-items-superseded-by-0008", "Order item deletion (superseded)", "Superseded by ADR 0008. Originally: delete items in application code before deleting an order.", "superseded", "2026-03-25"),
]


def write_docs():
    for slug, title, decision, status, date in ADRS:
        num = slug[:4]
        write(f"docs/adr/{slug}.md", f'''
            ---
            type: adr
            title: "{num}. {title}"
            status: {status}
            date: {date}
            issue: "none / ad-hoc"
            ---

            # {num}. {title}

            > {decision.split('. ')[0]}.

            ## Decision
            {decision}

            ## Consequences
            - Recorded so later work extends this rather than re-deciding it.
        ''')
    write("docs/api.md", '''
        # Public JSON API

        Consumed by the mobile app and the finance export. Field names and shapes are a contract; changing
        or removing one is a breaking change and needs a parallel-change plan.

        - `GET /customers` → `[{id, name, email, country, prices_include_vat}]`
        - `GET /invoices` → `[{number, customer_id, total (string, 2 dp), status, issued}]`
        - `POST /orders`, `POST /payments`, `POST /events/order.shipped`
        - `GET /reports/*` → read-only aggregates (see `services/api/reports/`)
    ''')
    write("docs/prd/invoice-csv-export.md", '''
        ---
        type: prd
        title: "PRD: Invoice CSV export"
        status: done
        issue: "#401"
        worklog: "./invoice-csv-export.worklog.md"
        ---

        # PRD: Invoice CSV export

        ## Functional requirements
        - **FR-001** — Export invoices as CSV with a header row: number, customer, total, status.
        - **FR-002** — Customer names containing commas or quotes are quoted.
        - **FR-003** — The export can be limited to one status or return all.

        ## Success criteria
        - **SC-001** — N invoices → N + 1 lines, every line 4 columns.
        - **SC-002** — `export(status="open")` contains only open invoices.
    ''')
    write("docs/prd/invoice-csv-export.worklog.md", '''
        ---
        type: worklog
        title: "Worklog: Invoice CSV export"
        status: done
        prd: "./invoice-csv-export.md"
        ---

        # Worklog: Invoice CSV export

        # Design
        ## Approach
        Pragmatic-balance: render in the request through `shared.csvio.to_csv`; filter in SQL.

        # Build Plan
        - [x] T1 — header + rows (`services/api/export.py`) + test
        - [x] T2 — quoting via the csv module + test (SC-001)
        - [x] T3 — status filter, parameterised + test (SC-002)

        ## Deviations (authorised)
        - 2026-08-12 — Export logs at INFO instead of DEBUG for the first weeks after launch; ops asked for it. Authorised by the user; revisit 2026-10-05.
    ''')
    write("docs/prd/monthly-statement-pdf.md", '''
        ---
        type: prd
        title: "PRD: Monthly statement PDF"
        status: clarified
        issue: "#440"
        worklog: "./monthly-statement-pdf.worklog.md"
        ---

        # PRD: Monthly statement PDF

        ## Functional requirements
        - **FR-001** — A per-customer statement for one calendar month: invoices, payments, opening and closing balance.
        - **FR-002** — Delivered as a PDF download.

        ## Success criteria
        - **SC-001** — Up to 500 invoices in the month, available within 3 seconds.
    ''')
    write("docs/prd/overdue-digest.md", '''
        ---
        type: prd
        title: "PRD: Overdue-invoice digest email"
        status: clarified
        issue: "#462"
        worklog: "./overdue-digest.worklog.md"
        ---

        # PRD: Overdue-invoice digest email

        > Once a day, each customer with overdue invoices gets one email listing them.

        ## Functional requirements
        - **FR-001** — Once per day, every customer with at least one overdue invoice receives a single digest email listing those invoices.
        - **FR-002** — A customer with no overdue invoices receives nothing.
        - **FR-003** — The same digest is not sent twice for the same customer and day.

        ## Success criteria
        - **SC-001** — On a day with N such customers, exactly N digest emails are sent.
        - **SC-002** — Re-running the daily job on the same day sends 0 additional emails.
    ''')
    write("docs/prd/payment-reminders.md", '''
        ---
        type: prd
        title: "PRD: Payment reminders"
        status: draft
        issue: "#470"
        worklog: "./payment-reminders.worklog.md"
        ---

        # PRD: Payment reminders

        > Email the customer before an invoice is due. Clarify pending.
    ''')
    write("docs/ledger.md", '''
        # Ledger

        Quick learnings, one dated line each; triaged at each feature's Capture phase.

        - 2026-08-14 — gotcha: `python3 -m unittest` from a service dir finds nothing; run discover from the repo root with `-t .`.
        - 2026-08-20 — gotcha: sqlite ignores foreign keys unless `PRAGMA foreign_keys=ON` per connection (ADR 0008 exists; keep it in `db.py`).
        - 2026-08-28 — decision: statements compute balances on the fly, never stored (agreed in the #440 clarify).
        - 2026-09-02 — note: notifications are sent by the worker, api only enqueues notify.* events.
        - 2026-09-05 — fact: Python dicts keep insertion order since 3.7.
        - 2026-09-08 — progress: finished T3 on #401; T4 next.
        - 2026-09-10 — pref: I like review findings grouped by severity, not by file.
        - 2026-09-12 — gotcha: `make snapshot` must run after every migration or the worker's snapshot_check job fails at 07:00.
    ''')
    write("README.md", '''
        # shop

        Monorepo: `services/api` (HTTP API, owns the schema), `services/worker` (scheduled and event-driven
        jobs, all outbound notifications), `web/` (frontend), `shared/` (helpers both services import).
        Each directory has its own CLAUDE.md with rules the root does not repeat.

        - Tests: `make test` (runs all three suites); per service see its CLAUDE.md.
        - Decisions: `docs/adr/`. Feature specs: `docs/prd/` (PRD + worklog). Quick learnings: `docs/ledger.md`.
        - Public API contract: `docs/api.md`.
    ''')
    write("CLAUDE.md", '''
        # shop — routing rules

        - New HTTP endpoints go in `services/api`. Scheduled or background work goes in `services/worker`.
        - `services/api` owns the database schema: migrations live in `services/api/migrations/`. After any
          migration, regenerate `services/worker/schema_snapshot.sql` (`make snapshot`) — a stale snapshot is a
          production incident (the worker's 07:00 `snapshot_check` job).
        - Feature flags are registered in BOTH `services/api/flags.py` and `web/src/flags.js`, named `<area>-<slug>`.
        - `web/` is the frontend; it never talks to the worker directly.
        - Helpers used by more than one service live in `shared/`; never copy one into a service.
        - Each service directory has its own CLAUDE.md with rules the root does not repeat. Read it.
        - Decisions with cross-service consequences are recorded in `docs/adr/` (immutable once accepted; supersede).
        - Tests: `make test`.
    ''')
    write("Makefile", '''
        .PHONY: test snapshot
        test:
        \tpython3 -m unittest discover -s shared/tests -t . && python3 -m unittest discover -s services/api/tests -t . && python3 -m unittest discover -s services/worker/tests -t .
        snapshot:
        \t( echo "-- generated by \\`make snapshot\\`; do not edit"; cat services/api/migrations/*.sql ) > services/worker/schema_snapshot.sql
    ''')
    write(".gitignore", "__pycache__/\n*.pyc\n.claude/shipgate.db*\n")


def write_config():
    write(".claude/shipgate.md", '''
        # shipgate — project config

        ## Knowledge base
        - PRD home: `docs/prd/`
        - ADR home: `docs/adr/`
        - Ledger: `docs/ledger.md`

        ## Journal
        - Database: `.claude/shipgate.db`

        ## Branching
        - Pattern: `<type>/<issue-id>-<slug>` (e.g. `feat/462-overdue-digest`, `fix/4xx-slug`)

        ## Autonomy
        - Mode: executive
        - Executive contract: the orchestrator makes and RECORDS routine decisions itself (clarify answers in the
          PRD's "Assumptions (executive)" list, design choices in the ADR) and reports them so the user can veto. It
          still escalates one-way doors (schema, public API, shared write paths, data migrations), user-visible
          scope changes, and genuine 50/50s.
    ''')
    write(".claude/shipgate.json", json.dumps({
        "version": 1, "db": ".claude/shipgate.db",
        "artifact_homes": {"prd": "docs/prd/*.md", "adr": "docs/adr/*.md", "worklog": "docs/prd/*.worklog.md"},
        "enforce": {"stop_gate": True, "auto_capture": True},
    }, indent=2) + "\n")


def seed_journal():
    conn = sqlite3.connect(".claude/shipgate.db")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, stream TEXT NOT NULL, version INTEGER NOT NULL,
          type TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data)), ts TEXT NOT NULL, actor TEXT,
          UNIQUE (stream, version));
        CREATE INDEX IF NOT EXISTS idx_events_stream ON events(stream, seq);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    for k, v in (("schema_version", "1"), ("created_at", "2026-08-10T09:00:00+00:00"), ("plugin_version", "0.13.5")):
        conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (k, v))
    streams = {
        "feat/401-invoice-csv-export": [
            ("2026-08-10T09:05:00+00:00", "flow-started", {"request": "Invoice CSV export (#401)", "branch": "feat/401-invoice-csv-export"}, "orchestrator"),
            ("2026-08-10T09:30:00+00:00", "phase-entered", {"phase": "route-and-map", "primary_home": "services/api", "touched": ["services/api"]}, "orchestrator"),
            ("2026-08-10T11:00:00+00:00", "clarify-passed", {"prd": "docs/prd/invoice-csv-export.md", "fr_count": 3, "sc_count": 2}, "orchestrator"),
            ("2026-08-11T10:00:00+00:00", "design-committed", {"issue": "401", "worklog": "docs/prd/invoice-csv-export.worklog.md", "adrs": ["docs/adr/0009-csv-export-synchronous.md"]}, "orchestrator"),
            ("2026-08-12T15:00:00+00:00", "verify-run", {"outcome": "pass", "task_ids": ["T1", "T2", "T3"], "commands": [{"cmd": "make test", "exit": 0, "tail": "Ran 19 tests OK"}]}, "orchestrator"),
            ("2026-08-12T15:01:00+00:00", "task-done", {"task_id": "T3"}, "orchestrator"),
            ("2026-08-13T10:00:00+00:00", "review-verdict", {"verdict": "ready", "findings": {"blocker": 0, "should_fix": 1, "nit": 2}}, "orchestrator"),
            ("2026-08-13T12:00:00+00:00", "capture-done", {"promoted": ["docs/adr/0009-csv-export-synchronous.md"], "dropped": []}, "orchestrator"),
            ("2026-08-13T12:01:00+00:00", "flow-completed", {"reason": "merged"}, "orchestrator"),
        ],
        "feat/462-overdue-digest": [
            ("2026-09-15T09:00:00+00:00", "flow-started", {"request": "Overdue-invoice digest email (#462)", "branch": "feat/462-overdue-digest"}, "orchestrator"),
            ("2026-09-15T09:40:00+00:00", "phase-entered", {"phase": "route-and-map", "primary_home": "services/worker", "touched": ["services/worker", "services/api"]}, "orchestrator"),
            ("2026-09-15T11:30:00+00:00", "clarify-passed", {"prd": "docs/prd/overdue-digest.md", "fr_count": 3, "sc_count": 2}, "orchestrator"),
        ],
        "feat/470-payment-reminders": [
            ("2026-09-18T09:00:00+00:00", "flow-started", {"request": "Payment reminders before due date (#470)", "branch": "feat/470-payment-reminders"}, "orchestrator"),
            ("2026-09-18T09:30:00+00:00", "phase-entered", {"phase": "route-and-map", "primary_home": "services/worker", "touched": ["services/worker", "shared"]}, "orchestrator"),
        ],
    }
    for stream, events in streams.items():
        for version, (ts, typ, data, actor) in enumerate(events, 1):
            conn.execute("INSERT INTO events (stream, version, type, data, ts, actor) VALUES (?, ?, ?, ?, ?, ?)",
                         (stream, version, typ, json.dumps(data), ts, actor))
    conn.commit()
    conn.close()


# ----------------------------------------------------------------------------- history
def build_history():
    """~60 commits, March→September 2026, with fix commits concentrated on three hot files."""
    sh("git", "init", "-q", "-b", "main")
    write_shared(); write_docs(); write_config()
    # scaffold commits
    commit("2026-03-02", "feat: repo scaffold — shared helpers, docs, routing rules")
    write_api(); commit("2026-03-05", "feat(api): customers, invoices, orders, pricing, routes")
    write_worker(); commit("2026-03-09", "feat(worker): schedule, shipping, notifications, retry job")
    write_web(); commit("2026-03-12", "feat(web): pages, components, api client")
    sh("make", "snapshot"); commit("2026-03-13", "chore(worker): regenerate schema snapshot")
    # feature + fix history
    hot_routes = ["fix(api): clamp limit on GET /invoices", "fix(api): 404 instead of 500 for unknown customer", "fix(api): duplicate order on client retry",
                  "fix(api): on_shipped ignores unknown order", "fix(api): wrong status code on POST /orders", "fix(api): pagination off by one on /invoices",
                  "fix(api): carrier_ref validation", "fix(api): reject empty items", "fix(api): payments route missing from table", "fix(api): health route registered twice",
                  "fix(api): flags route leaked internal names", "fix(api): statements route guarded by admin"]
    hot_pricing = ["fix(pricing): discount applied before quantity", "fix(pricing): negative discount rejected", "fix(pricing): float unit prices via str()",
                   "fix(pricing): discount over 100 clamps", "fix(pricing): rounding of .005", "fix(pricing): empty order totals 0.00", "fix(pricing): discount percent as Decimal", "fix(pricing): quantity zero"]
    hot_web = ["fix(web): OrderList status badge for cancelled", "fix(web): OrderList money sign", "fix(web): OrderList empty state", "fix(web): OrderList flag gate"]
    dates = iter([f"2026-0{m}-{d:02d}" for m in range(3, 10) for d in (14, 16, 18, 20, 22, 24, 26, 28) if not (m == 9 and d > 6)])
    seq = []
    seq += [("routes", m) for m in hot_routes[:4]] + [("pricing", m) for m in hot_pricing[:3]] + [("web", hot_web[0])]
    seq += [("feat", "feat(api): payments recording + matcher job"), ("feat", "feat(worker): snapshot_check job"), ("feat", "feat(web): reports page")]
    seq += [("routes", m) for m in hot_routes[4:8]] + [("pricing", m) for m in hot_pricing[3:6]] + [("web", hot_web[1])]
    seq += [("feat", "feat(api): audit log (ADR 0011)"), ("feat", "feat(api): reports/aging"), ("docs", "docs: ADR 0010 web never formats money")]
    seq += [("routes", m) for m in hot_routes[8:]] + [("pricing", m) for m in hot_pricing[6:]] + [("web", hot_web[2]), ("web", hot_web[3])]
    seq += [("feat", "feat(api): invoice CSV export (#401, T1-T3)"), ("docs", "docs: PRD #440 monthly statements clarified"), ("docs", "docs: PRD #462 overdue digest clarified"),
            ("feat", "feat(api): statements opening balance (#440 spike)"), ("docs", "docs: ledger entries from #401 capture"), ("chore", "chore: gitignore the journal db")]
    n = 0
    for kind, msg in seq:
        n += 1
        day = next(dates)
        if kind == "routes":
            append("services/api/routes.py", f"\n# {msg}\n")
        elif kind == "pricing":
            append("services/api/pricing.py", f"\n# {msg}\n")
        elif kind == "web":
            append("web/src/components/OrderList.js", f"\n// {msg}\n")
        else:
            append("docs/CHANGES.md", f"- {day} — {msg}\n")
        commit(day, msg)


# ----------------------------------------------------------------------------- variants
def plant(variant):
    if variant == "regression":
        # a "refactor" at the end of August switched the rounding mode; later commits bury it
        replace("services/api/pricing.py", "from decimal import Decimal, ROUND_HALF_UP", "from decimal import Decimal, ROUND_DOWN")
        replace("services/api/pricing.py", "return discounted.quantize(CENT, rounding=ROUND_HALF_UP)", "return discounted.quantize(CENT, rounding=ROUND_DOWN)")
        commit("2026-09-08", "refactor(pricing): simplify rounding")
        append("services/api/pricing.py", "\nTAX_RATE = Decimal(\"0.20\")\n"); commit("2026-09-11", "chore(pricing): add TAX_RATE constant")
        append("services/api/routes.py", "\n# chore(api): route table comment\n"); commit("2026-09-14", "chore(api): route table comment")
    elif variant == "selective":
        replace("services/api/invoices.py", "    price = Decimal(item[\"price\"])\n    return price * item[\"qty\"]",
                "    price = Decimal(item[\"price\"])\n    if customer[\"prices_include_vat\"]:\n        price = to_gross(price, customer[\"country\"])\n    return price * item[\"qty\"]")
        commit("2026-09-09", "feat(invoices): support VAT-inclusive price lists (ADR 0006)")
        append("services/api/routes.py", "\n# chore(api): comment\n"); commit("2026-09-12", "chore(api): comment")
    elif variant == "review-planted":
        write("docs/prd/cancel-order.md", "---\ntype: prd\ntitle: \"PRD: Cancel an order\"\nstatus: clarified\nissue: \"#455\"\n---\n\n# PRD: Cancel an order\n\n- **FR-001** — `POST /orders/{id}/cancel` moves a placed order to cancelled.\n- **FR-002** — Shipped orders cannot be cancelled (409).\n- **SC-001** — Cancelling a placed order sets status cancelled and emits `order.cancelled`.\n")
        write("docs/prd/cancel-order.worklog.md", "---\ntype: worklog\ntitle: \"Worklog: Cancel an order\"\nprd: \"./cancel-order.md\"\n---\n\n# Worklog: Cancel an order\n\n# Build Plan\n- [x] T1 — cancel_order in orders.py + route + test\n\n## Deviations (authorised)\n- 2026-09-16 — cancel logs at INFO (CLAUDE.md says DEBUG) for the launch fortnight; ops asked. Authorised by the user.\n")
        commit("2026-09-16", "docs: PRD #455 cancel order")
        append("services/api/orders.py", '''

def cancel_order(db, bus, order_id, reason):
    from shared.logging_ import log
    log.info("cancel requested for order %s: %s", order_id, reason)
    row = db.query(f"SELECT status FROM orders WHERE id = {order_id}")
    if row[0][0] == "shipped":
        raise Conflict(f"order {order_id} already shipped")
    db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", order_id)
    bus.emit("order.cancelled", order_id=order_id, reason=reason)
''')
        replace("services/api/handlers/orders.py", "def on_shipped(req, db, bus=None):", "def cancel(req, db, bus=None):\n    orders.cancel_order(db, bus, req[\"id\"], req.get(\"reason\"))\n    return {\"ok\": True}\n\n\ndef on_shipped(req, db, bus=None):")
        append("services/api/routes.py", "\nroute(\"POST\", \"/orders/{id}/cancel\")(h_orders.cancel)\n")
        commit("2026-09-17", "feat(api): cancel-order endpoint (#455 T1)")
    elif variant == "review-after-fixes":
        # round 0: a feature commit that introduced the two findings
        PARAM = '        records = db.query("SELECT i.number, c.name, i.total, i.status FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.status = ?", status)'
        FSTR = '        records = db.query(f"SELECT i.number, c.name, i.total, i.status FROM invoices i JOIN customers c ON c.id = i.customer_id WHERE i.status = \'{status}\'")'
        FMT = "    return [(number, customer, fmt(total), status) for number, customer, total, status in records]"
        INLINE = '    return [(number, customer, f"{total // 100}.{total % 100:02d}", status) for number, customer, total, status in records]'
        replace("services/api/export.py", PARAM, FSTR)
        replace("services/api/export.py", FMT, INLINE)
        commit("2026-09-16", "feat(export): status filter + formatted totals")
        # round 1 findings recorded, then the fix commit that resolves them and quietly drops the header
        append("docs/prd/invoice-csv-export.worklog.md", "\n## Review round 1 (2026-09-18)\n- F1 — `export()` builds the status filter by string formatting (CLAUDE.md: parameterise). **Fixed at HEAD.**\n- F2 — `export_rows` formats money inline instead of via `shared.money.fmt`. **Fixed at HEAD.**\n")
        replace("services/api/export.py", FSTR, PARAM)
        replace("services/api/export.py", INLINE, FMT)
        replace("services/api/export.py", "    return to_csv(HEADER, export_rows(records))", "    rows = export_rows(records)\n    return to_csv(rows[0] if rows else HEADER, rows[1:])  # header now derived from the first row")
        replace("services/api/tests/test_export.py", "        self.assertEqual(rows[0], [\"number\", \"customer\", \"total\", \"status\"])\n", "")
        commit("2026-09-19", "fix(export): parameterise filter; format via shared.money (review F1, F2)")
    elif variant == "one-line":
        pass
    # route / recall / clarify / design variants need no plant: the shared repo carries the rules, ADRs and PRDs.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="base")
    args = ap.parse_args()
    build_history()
    plant(args.variant)
    seed_journal()


if __name__ == "__main__":
    main()

PYGEN
