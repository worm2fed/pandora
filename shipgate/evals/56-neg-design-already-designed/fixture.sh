#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
mkdir -p docs/prd docs/adr services/api/migrations services/worker
cat > README.md <<'EOF_F'
# billing

`services/api` — HTTP API (owns the schema, `services/api/migrations/`). `services/worker` — background jobs and all outbound notifications. Docs: `docs/prd/` (PRD + `<name>.worklog.md`), `docs/adr/`.
EOF_F
cat > CLAUDE.md <<'EOF_F'
# billing — conventions

- New HTTP endpoints go in `services/api`; scheduled/background work in `services/worker`.
- `services/api` owns the schema: migrations in `services/api/migrations/`; regenerate `services/worker/schema_snapshot.sql` after any migration.
- `docs/api.md` is a public contract (mobile app + finance export consume it): changing a field's shape is a breaking change and needs a parallel-change plan.
- SQL is always parameterised. Money is formatted only via `services/api/money.py`.
- Tests: `python3 -m unittest` in each service directory.
- PRDs: `docs/prd/<feature>.md`; worklog beside it as `<feature>.worklog.md`; ADRs `docs/adr/NNNN-<title>.md`, immutable once accepted (supersede, don't edit).
EOF_F
cat > docs/api.md <<'EOF_F'
# Public JSON API

## GET /invoices
Returns `[{number, customer, total (string, 2 dp), status}]`. Consumed by the mobile app and the finance export.

## GET /customers
Returns `[{id, name, email}]`.
EOF_F
cat > docs/adr/0001-api-owns-schema.md <<'EOF_F'
---
type: adr
title: "0001. api owns the schema"
status: accepted
date: 2026-05-10
issue: "none / ad-hoc"
---

# 0001. api owns the schema

> Migrations live in services/api; the worker reads a generated snapshot.

## Decision
Only `services/api` runs migrations. The worker never migrates; it reads `schema_snapshot.sql` regenerated after each migration.
EOF_F
cat > docs/adr/0002-notifications-go-through-worker.md <<'EOF_F'
---
type: adr
title: "0002. All customer notifications are sent by the worker"
status: accepted
date: 2026-06-02
issue: "#388"
---

# 0002. All customer notifications are sent by the worker

> api enqueues `notify.*` events; the worker delivers them with retries and rate limiting.

## Decision
Every outbound customer notification (email, SMS, push) is sent by `services/worker`. `services/api` never sends; it emits a `notify.*` event with recipient and template.

## Consequences
- A new notification = a new event emitted by api + a handler in the worker's `notifications.py`.
EOF_F
cat > services/api/export.py <<'EOF_F'
"""Invoice CSV export (shipped)."""
import csv
import io

HEADER = ("number", "customer", "total", "status")


def export(records):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    w.writerows(records)
    return buf.getvalue()
EOF_F
cat > services/api/money.py <<'EOF_F'
def fmt(cents):
    return f"{cents // 100}.{cents % 100:02d}"
EOF_F
cat > services/api/invoices.py <<'EOF_F'
"""Invoice model + queries."""


def list_invoices(db, status=None):
    if status:
        return db.query("SELECT number, customer, total, status FROM invoices WHERE status = ?", status)
    return db.query("SELECT number, customer, total, status FROM invoices")
EOF_F
cat > services/api/migrations/0001_invoices.sql <<'EOF_F'
CREATE TABLE invoices (
  number TEXT PRIMARY KEY,
  customer TEXT NOT NULL,
  total INTEGER NOT NULL,
  status TEXT NOT NULL,
  issued DATE NOT NULL
);
EOF_F
cat > services/worker/schema_snapshot.sql <<'EOF_F'
-- generated; do not edit
CREATE TABLE invoices (
  number TEXT PRIMARY KEY,
  customer TEXT NOT NULL,
  total INTEGER NOT NULL,
  status TEXT NOT NULL,
  issued DATE NOT NULL
);
EOF_F
cat > services/worker/notifications.py <<'EOF_F'
"""Delivers notify.* events (ADR 0002)."""
TEMPLATES = {"notify.order_shipped": "Your order {order_id} has shipped."}


def on_notify(mailer, event):
    mailer.send(event["recipient"], TEMPLATES[event["type"]].format(**event))
EOF_F
cat > services/worker/schedule.py <<'EOF_F'
SCHEDULE = {}
EOF_F
cat > docs/prd/invoice-paid-at.md <<'EOF_F'
---
type: prd
title: "PRD: Show when an invoice was paid"
status: clarified
issue: "#451"
worklog: "./invoice-paid-at.worklog.md"
---

# PRD: Show when an invoice was paid

> Record the moment an invoice is marked paid and show it in the invoice list.

## Functional requirements
- **FR-001** — When an invoice becomes `paid`, the timestamp is recorded.
- **FR-002** — The invoice list shows the paid timestamp for paid invoices (empty for open ones).

## Success criteria
- **SC-001** — Marking an invoice paid and listing it shows the recorded timestamp; open invoices show none.

## Constraints & assumptions
- Additive change; the public API gains one optional field (`paid_at`, ISO string or null) — no existing field changes.
EOF_F
cat > docs/prd/invoice-paid-at.worklog.md <<'EOF_F'
---
type: worklog
title: "Worklog: Show when an invoice was paid"
status: building
prd: "./invoice-paid-at.md"
---

# Worklog: Show when an invoice was paid

# Design

## Approach
Minimal change: one nullable column, set in the state change, surfaced in the list query.

## Data model / schema
- Migration `0002_invoices_paid_at.sql`: `ALTER TABLE invoices ADD COLUMN paid_at TIMESTAMP NULL`; regenerate the worker snapshot.

# Build Plan
- [ ] T1 — migration 0002 + snapshot refresh (`services/api/migrations/`, `services/worker/schema_snapshot.sql`); done = both files updated, tests pass.
- [ ] T2 — set `paid_at` when status becomes paid (`services/api/invoices.py`) + test; done = test shows the timestamp.
- [ ] T3 — include `paid_at` in `GET /invoices` (`docs/api.md` additive field) + test.
EOF_F
c 2026-09-15 "feat: billing base with PRDs and ADRs"
