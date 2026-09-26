#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
cat > vat.py <<'PY'
from decimal import Decimal

VAT_RATES = {"DE": Decimal("0.19"), "FR": Decimal("0.20"), "US": Decimal("0")}


def to_gross(net, country):
    return net * (1 + VAT_RATES[country])


def to_net(gross, country):
    return gross / (1 + VAT_RATES[country])
PY
cat > fx.py <<'PY'
from decimal import Decimal, ROUND_HALF_EVEN

RATES = {"USD": Decimal("1"), "EUR": Decimal("1")}  # book currency == invoice currency for now


def convert(amount, currency):
    # TODO: banker's rounding here? finance never confirmed
    return (amount * RATES[currency]).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
PY
cat > invoice.py <<'PY'
from decimal import Decimal

from fx import convert
from vat import to_gross


def line_amount(item, customer):
    return Decimal(item["price"]) * item["qty"]


def invoice_total(items, customer):
    net = sum((line_amount(i, customer) for i in items), Decimal(0))
    return convert(to_gross(net, customer["country"]), customer["currency"])


def credit_note_total(items, customer):
    return -invoice_total(items, customer)
PY
cat > test_invoice.py <<'PY'
import unittest
from decimal import Decimal

from invoice import invoice_total

US = {"country": "US", "currency": "USD", "prices_include_vat": False}
DE = {"country": "DE", "currency": "EUR", "prices_include_vat": True}


class InvoiceTotalTest(unittest.TestCase):
    def test_us_customer(self):
        self.assertEqual(invoice_total([{"price": "100.00", "qty": 2}], US), Decimal("200.00"))


if __name__ == "__main__":
    unittest.main()
PY
c 2026-09-10 "feat: invoice totals with VAT"
printf '# invoicing\n\nRun tests: `python3 -m unittest`\n' > README.md
c 2026-09-12 "docs: add README"
python3 - <<'PY'
s = open("invoice.py").read()
s = s.replace("""def line_amount(item, customer):
    return Decimal(item["price"]) * item["qty"]""", """def line_amount(item, customer):
    price = Decimal(item["price"])
    if customer["prices_include_vat"]:
        price = to_gross(price, customer["country"])
    return price * item["qty"]""")
open("invoice.py", "w").write(s)
PY
c 2026-09-17 "feat: support VAT-inclusive price lists"
python3 - <<'PY'
s = open("fx.py").read()
s = s.replace('RATES = {"USD": Decimal("1"), "EUR": Decimal("1")}', 'RATES = {"USD": Decimal("1"), "EUR": Decimal("1"), "GBP": Decimal("1")}')
open("fx.py", "w").write(s)
PY
c 2026-09-19 "feat(fx): add GBP"
