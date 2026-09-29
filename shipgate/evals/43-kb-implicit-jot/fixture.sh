#!/usr/bin/env bash
# Scaffold: builds the synthetic monorepo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
mkdir -p services/api/migrations services/api/reports services/worker web/src/components docs/adr
cat > README.md <<'EOF_F'
# shop

Monorepo: `services/api` (HTTP API, owns the schema), `services/worker` (scheduled and event-driven jobs), `web/` (frontend). See each directory's CLAUDE.md.
EOF_F
cat > CLAUDE.md <<'EOF_F'
# shop — routing rules

- New HTTP endpoints go in `services/api`. Scheduled or background work goes in `services/worker`.
- `services/api` owns the database schema: migrations live in `services/api/migrations/`.
  After any migration, regenerate `services/worker/schema_snapshot.sql` (`make snapshot`) — the
  worker reads the schema from that file, and a stale snapshot is a production incident.
- Feature flags are registered in BOTH `services/api/flags.py` and `web/src/flags.js`, named
  `<area>-<slug>`.
- `web/` is the frontend; it never talks to the worker directly.
- Each service directory has its own CLAUDE.md with rules the root does not repeat. Read it.
- Decisions with cross-service consequences are recorded in `docs/adr/`.
EOF_F
cat > services/api/CLAUDE.md <<'EOF_F'
# services/api

- Endpoints are registered in `routes.py`; handlers live next to their domain module.
- Read-only reporting endpoints (aggregates, exports, dashboards) go under `reports/`, never in
  `routes.py` — they are mounted separately so they can be rate-limited and cached as a group.
- Order state changes (placed, shipped, cancelled) happen only here, in `orders.py`.
- Tests: `python3 -m unittest` from this directory.
EOF_F
cat > services/worker/CLAUDE.md <<'EOF_F'
# services/worker

- The worker never writes to the order tables. It consumes `order.*` events, does the slow work
  (carrier booking, notifications, recomputation) and emits result events that `services/api`
  applies. Anything that mutates orders belongs in `services/api`.
- Scheduled jobs are registered in `schedule.py`.
- The schema the worker reads is `schema_snapshot.sql` — regenerated from api's migrations, never edited by hand.
EOF_F
cat > web/CLAUDE.md <<'EOF_F'
# web

- Components live in `src/components/`; the order list is `src/components/OrderList.js`.
- Money is formatted only through `src/money.js`; never format money inside a component.
- Feature flags come from `src/flags.js`.
EOF_F
cat > docs/adr/0002-notifications-go-through-worker.md <<'EOF_F'
# ADR 0002 — All customer notifications are sent by the worker

Status: accepted (2026-06-02)

## Decision
Every outbound customer notification (email, SMS, push) is sent by `services/worker`. `services/api`
never sends; it enqueues a `notify.*` event with the recipient and template, and the worker delivers
it with retries and rate limiting.

## Consequences
- A new notification = a new event emitted by api + a handler in the worker's `notifications.py`.
- Delivery status is written back by the worker as a `notify.delivered` / `notify.failed` event.
EOF_F
cat > services/api/config.py <<'EOF_F'
PAGE_SIZE = 20
DATABASE_URL = "sqlite:///shop.db"
EOF_F
cat > services/api/flags.py <<'EOF_F'
FLAGS = {
    "orders-bulk-cancel": False,
}
EOF_F
cat > services/api/orders.py <<'EOF_F'
"""Order state machine — the only place order rows change."""
from datetime import datetime

STATES = ("placed", "shipped", "cancelled")


def place_order(db, customer_id, items):
    order_id = db.insert("orders", customer_id=customer_id, status="placed", placed_at=datetime.utcnow())
    db.emit("order.placed", order_id=order_id)
    return order_id


def apply_shipped(db, order_id, carrier_ref):
    """Applied when the worker emits order.shipped."""
    db.update("orders", order_id, status="shipped", carrier_ref=carrier_ref)
    db.emit("notify.order_shipped", order_id=order_id)
EOF_F
cat > services/api/routes.py <<'EOF_F'
from orders import apply_shipped, place_order

ROUTES = {}


def route(method, path):
    def deco(fn):
        ROUTES[(method, path)] = fn
        return fn
    return deco


@route("POST", "/orders")
def create_order(req, db):
    return {"id": place_order(db, req["customer_id"], req["items"])}


@route("GET", "/orders")
def list_orders(req, db):
    return db.select("orders", limit=req.get("limit", 20))


@route("POST", "/events/order.shipped")
def on_shipped(req, db):
    apply_shipped(db, req["order_id"], req["carrier_ref"])
    return {"ok": True}
EOF_F
cat > services/api/reports/__init__.py <<'EOF_F'

EOF_F
cat > services/api/reports/customers.py <<'EOF_F'
"""Read-only reporting endpoints, mounted under /reports."""


def orders_per_customer(db, since):
    return db.query("SELECT customer_id, COUNT(*) FROM orders WHERE placed_at >= ? GROUP BY customer_id", since)
EOF_F
cat > services/api/migrations/0001_orders.sql <<'EOF_F'
CREATE TABLE orders (
  id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL,
  status TEXT NOT NULL,
  placed_at TIMESTAMP NOT NULL,
  carrier_ref TEXT,
  total NUMERIC(12, 2)
);
EOF_F
cat > services/worker/schema_snapshot.sql <<'EOF_F'
-- generated by `make snapshot`; do not edit
CREATE TABLE orders (
  id INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL,
  status TEXT NOT NULL,
  placed_at TIMESTAMP NOT NULL,
  carrier_ref TEXT,
  total NUMERIC(12, 2)
);
EOF_F
cat > services/worker/schedule.py <<'EOF_F'
from jobs import retry_failed_notifications

SCHEDULE = {
    "*/15 * * * *": retry_failed_notifications,
}
EOF_F
cat > services/worker/jobs.py <<'EOF_F'
def retry_failed_notifications(bus):
    for ev in bus.pending("notify.failed"):
        bus.emit("notify.retry", **ev)
EOF_F
cat > services/worker/shipping.py <<'EOF_F'
"""Consumes order.placed, books the carrier, emits order.shipped."""


def on_order_placed(bus, carrier, order_id):
    ref = carrier.book(order_id)
    bus.emit("order.shipped", order_id=order_id, carrier_ref=ref)
EOF_F
cat > services/worker/notifications.py <<'EOF_F'
"""Delivers notify.* events (ADR 0002)."""
TEMPLATES = {"notify.order_shipped": "Your order {order_id} has shipped."}


def on_notify(mailer, event):
    mailer.send(event["recipient"], TEMPLATES[event["type"]].format(**event))
EOF_F
cat > web/src/flags.js <<'EOF_F'
export const FLAGS = { 'orders-bulk-cancel': false };
EOF_F
cat > web/src/money.js <<'EOF_F'
export const formatMoney = (cents) => `$${(cents / 100).toFixed(2)}`;
EOF_F
cat > web/src/components/OrderList.js <<'EOF_F'
import { formatMoney } from '../money.js';

export function OrderList({ orders }) {
  return orders.map((o) => `${o.id} ${o.status} ${formatMoney(o.total)}`).join('\n');
}
EOF_F
cat > Makefile <<'EOF_F'
snapshot:
	cat services/api/migrations/*.sql > services/worker/schema_snapshot.sql
EOF_F
c 2026-06-01 "feat: shop monorepo — api, worker, web"
cat > docs/ledger.md <<'EOF_F'
# Ledger

Quick learnings, one dated line each; triaged at each feature's Capture phase.
EOF_F
cat > services/api/db.py <<'EOF_F'
"""Tiny sqlite helper used by the api tests."""
import sqlite3


def connect(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.executescript(open("migrations/0001_orders.sql").read())
    conn.executescript(open("migrations/0002_order_items.sql").read())
    return conn
EOF_F
cat > services/api/migrations/0002_order_items.sql <<'EOF_F'
CREATE TABLE order_items (
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  sku TEXT NOT NULL,
  qty INTEGER NOT NULL
);
EOF_F
cat > services/api/test_db.py <<'EOF_F'
import unittest

from db import connect


class CascadeTest(unittest.TestCase):
    def test_cascade_delete(self):
        conn = connect()
        conn.execute("INSERT INTO orders (id, customer_id, status, placed_at) VALUES (1, 7, 'placed', '2026-09-01')")
        conn.execute("INSERT INTO order_items (order_id, sku, qty) VALUES (1, 'A-1', 2)")
        conn.execute("DELETE FROM orders WHERE id = 1")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
EOF_F
printf '\nTests: `python3 -m unittest` from `services/api/`.\n' >> README.md
c 2026-09-05 "docs: knowledge base state; order_items table + cascade test"
