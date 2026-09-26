#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
cat > pricing.py <<'PY'
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
PY
cat > test_pricing.py <<'PY'
import unittest
from decimal import Decimal

from pricing import order_total


class OrderTotalTest(unittest.TestCase):
    def test_discount(self):
        self.assertEqual(order_total([(19.99, 3)], 15), Decimal("50.97"))

    def test_no_discount(self):
        self.assertEqual(order_total([(10, 1)]), Decimal("10.00"))

    def test_fractional_unit_price(self):
        self.assertEqual(order_total([(0.333, 3)]), Decimal("1.00"))


if __name__ == "__main__":
    unittest.main()
PY
c 2026-09-14 "feat: order totals with percentage discounts"
printf '# pricing\n\nRun tests: `python3 -m unittest`\n' > README.md
c 2026-09-16 "docs: add README"
python3 - <<'PY'
import re
s = open("pricing.py").read()
s = s.replace("from decimal import Decimal, ROUND_HALF_UP", "from decimal import Decimal, ROUND_DOWN")
s = s.replace("""    discounted = amount * (Decimal(100) - Decimal(str(percent))) / Decimal(100)
    return discounted.quantize(CENT, rounding=ROUND_HALF_UP)""", """    discounted = amount * (100 - Decimal(str(percent))) / 100
    return discounted.quantize(CENT, rounding=ROUND_DOWN)""")
open("pricing.py", "w").write(s)
PY
c 2026-09-18 "refactor: simplify rounding"
python3 - <<'PY'
s = open("pricing.py").read()
s = s.replace('CENT = Decimal("0.01")\n', 'CENT = Decimal("0.01")\nTAX_RATE = Decimal("0.20")\n')
open("pricing.py", "w").write(s)
PY
c 2026-09-21 "chore: add TAX_RATE constant"
