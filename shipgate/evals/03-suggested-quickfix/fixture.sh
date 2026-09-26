#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
cat > customers.py <<'PY'
_STORE = {}


def save_customer(customer):
    _STORE[customer["ref"]] = customer


def lookup(ref):
    return _STORE.get(ref)
PY
cat > order_sync.py <<'PY'
from customers import lookup


def sync_orders(orders):
    synced = []
    for order in orders:
        customer = lookup(order["customer_ref"])
        synced.append({
            "order_id": order["id"],
            "customer_id": customer["id"],
            "amount": order["amount"],
        })
    return synced
PY
cat > sync.py <<'PY'
from customers import save_customer
from order_sync import sync_orders

save_customer({"id": 1, "ref": "ACME-01", "name": "Acme"})
save_customer({"id": 2, "ref": "Globex-7 ", "name": "Globex"})

print(sync_orders([
    {"id": 100, "customer_ref": "ACME-01", "amount": 40},
    {"id": 101, "customer_ref": "Globex-7 ", "amount": 15},
]))
PY
c 2026-09-08 "feat: nightly order sync"
python3 - <<'PY'
s = open("customers.py").read()
s = s.replace('    _STORE[customer["ref"]] = customer', '    # refs arrive with stray case/whitespace from the CRM import\n    _STORE[customer["ref"].strip().lower()] = customer')
open("customers.py", "w").write(s)
PY
c 2026-09-15 "perf: normalize customer keys on save"
printf '# order sync\n\nRun: `python3 sync.py`\n' > README.md
c 2026-09-16 "docs: add README"
