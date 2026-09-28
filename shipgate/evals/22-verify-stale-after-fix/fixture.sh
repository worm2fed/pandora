#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
cat > README.md <<'EOF_F'
# pricing

Tests: `python3 -m unittest`
EOF_F
cat > pricing.py <<'EOF_F'
from decimal import Decimal, ROUND_DOWN

CENT = Decimal("0.01")


def subtotal(items):
    return sum(price * qty for price, qty in items)


def order_total(items, discount_percent=0):
    net = subtotal(items) * (1 - Decimal(discount_percent) / 100)
    return net.quantize(CENT, rounding=ROUND_DOWN)
EOF_F
cat > test_pricing.py <<'EOF_F'
import unittest
from decimal import Decimal

from pricing import order_total


class OrderTotalTest(unittest.TestCase):
    def test_no_discount(self):
        self.assertEqual(order_total([(19.99, 3)]), Decimal("59.97"))

    def test_rounding(self):
        self.assertEqual(order_total([(0.333, 3)]), Decimal("1.00"))


if __name__ == "__main__":
    unittest.main()
EOF_F
c 2026-09-10 "feat: pricing"
