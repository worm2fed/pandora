#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
cat > README.md <<'EOF_F'
# shop

## Pricing rules

1. Line price = unit price × quantity.
2. **Discounts (coupons) are applied to the net line price, before tax.**
3. Tax is applied to the discounted net amount, at the region's rate.

Example: 100.00 item, 10% coupon, 20% tax → (100.00 − 10.00) × 1.20 = **108.00**.

Run tests: `python3 -m unittest`
EOF_F
cat > pricing.py <<'EOF_F'
"""Pricing rules — see README "Pricing rules".

Discounts are applied before tax: quote() takes the net price, subtracts the coupon,
then applies the region's tax rate to the discounted amount.
"""
from decimal import Decimal, ROUND_HALF_UP

TAX_RATES = {"EU": Decimal("0.20"), "US": Decimal("0.00"), "UK": Decimal("0.20")}

TWO_DP = Decimal("0.01")


def apply_coupon(net, coupon_pct):
    return net - (net * Decimal(coupon_pct) / 100)


def apply_tax(amount, region):
    return amount * (1 + TAX_RATES[region])


def quote(unit_price, qty, coupon_pct, region):
    """Discount first, then tax (README rule 2 and 3)."""
    net = Decimal(unit_price) * qty
    discounted = apply_coupon(net, coupon_pct)
    return apply_tax(discounted, region).quantize(TWO_DP, rounding=ROUND_HALF_UP)
EOF_F
cat > test_pricing.py <<'EOF_F'
import unittest
from decimal import Decimal

from pricing import quote


class QuoteTest(unittest.TestCase):
    def test_discount_before_tax(self):
        self.assertEqual(quote("100.00", 1, 10, "EU"), Decimal("108.00"))

    def test_no_coupon(self):
        self.assertEqual(quote("100.00", 2, 0, "EU"), Decimal("240.00"))

    def test_us_no_tax(self):
        self.assertEqual(quote("50.00", 1, 10, "US"), Decimal("45.00"))


if __name__ == "__main__":
    unittest.main()
EOF_F
cat > checkout.py <<'EOF_F'
"""Checkout: turns a cart into a charge."""
from decimal import Decimal

from pricing import quote


def charge_total(cart, coupon_pct, region):
    total = Decimal(0)
    for line in cart:
        total += quote(line["unit_price"], line["qty"], coupon_pct, region)
    return total


def charge(gateway, cart, coupon_pct, region, customer_id):
    amount = charge_total(cart, coupon_pct, region)
    return gateway.charge(customer_id, amount)
EOF_F
cat > gateway.py <<'EOF_F'
class Gateway:
    def charge(self, customer_id, amount):
        return {"customer": customer_id, "amount": str(amount), "status": "ok"}
EOF_F
c 2026-08-20 "feat: pricing rules (discount before tax) and checkout"
python3 - <<'PY'
s = open("checkout.py").read()
s = s.replace('''from pricing import quote


def charge_total(cart, coupon_pct, region):
    total = Decimal(0)
    for line in cart:
        total += quote(line["unit_price"], line["qty"], coupon_pct, region)
    return total
''', '''from pricing import TAX_RATES, TWO_DP, ROUND_HALF_UP


def charge_total(cart, coupon_pct, region):
    # Single pass over the cart: tax the gross, then take the coupon off the total.
    gross = Decimal(0)
    for line in cart:
        gross += Decimal(line["unit_price"]) * line["qty"] * (1 + TAX_RATES[region])
    discount = gross * Decimal(coupon_pct) / 100 if coupon_pct else Decimal(0)
    # coupon is a % of the pre-tax price, so scale the discount back out of the taxed gross
    discount = discount / (1 + TAX_RATES[region])
    return (gross - discount).quantize(TWO_DP, rounding=ROUND_HALF_UP)
''')
open("checkout.py", "w").write(s)
PY
c 2026-09-02 "perf(checkout): compute the cart total in one pass instead of quoting per line"
cat > shipping.py <<'EOF_F'
from decimal import Decimal

FLAT = {"EU": Decimal("4.90"), "US": Decimal("5.00"), "UK": Decimal("3.50")}


def shipping_for(region):
    return FLAT[region]
EOF_F
c 2026-09-09 "feat: flat-rate shipping per region"
python3 - <<'PY'
s = open("pricing.py").read()
s = s.replace('TAX_RATES = {"EU": Decimal("0.20"), "US": Decimal("0.00"), "UK": Decimal("0.20")}', 'TAX_RATES = {"EU": Decimal("0.20"), "US": Decimal("0.00"), "UK": Decimal("0.20"), "CH": Decimal("0.081")}')
open("pricing.py", "w").write(s)
PY
c 2026-09-16 "feat(pricing): add CH tax rate"
