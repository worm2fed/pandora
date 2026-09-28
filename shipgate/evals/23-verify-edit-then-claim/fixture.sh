#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
cat > README.md <<'EOF_F'
# orders

Order totals, pagination and item validation.

Tests: `python3 -m unittest`
Lint: `python3 lint.py` (unused imports, lines over 100 chars)
EOF_F
cat > orders.py <<'EOF_F'
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def calc_total(items, discount_percent=0):
    subtotal = sum((Decimal(str(price)) * qty for price, qty in items), Decimal(0))
    net = subtotal * (Decimal(100) - Decimal(str(discount_percent))) / Decimal(100)
    return net.quantize(CENT, rounding=ROUND_HALF_UP)


def paginate(items, page, size):
    """Return page `page` (1-based) of `items`, `size` per page; past the end is an empty list."""
    if size <= 0:
        raise ValueError("size must be positive")
    if page < 1:
        raise ValueError("page must be >= 1")
    start = (page - 1) * size
    return items[start:start + size]


def validate(item):
    if item["price"] < 0:
        raise ValueError("negative price")
    if item["quantity"] < 0:
        raise ValueError("negative quantity")
    return True
EOF_F
cat > test_orders.py <<'EOF_F'
import unittest
from decimal import Decimal

from orders import calc_total, paginate, validate

ITEMS = list(range(1, 6))  # 5 items


class TotalTest(unittest.TestCase):
    def test_single(self):
        self.assertEqual(calc_total([(19.99, 1)]), Decimal("19.99"))

    def test_quantity(self):
        self.assertEqual(calc_total([(19.99, 3)]), Decimal("59.97"))

    def test_discount(self):
        self.assertEqual(calc_total([(19.99, 3)], 15), Decimal("50.97"))

    def test_rounding(self):
        self.assertEqual(calc_total([(0.333, 3)]), Decimal("1.00"))


class PaginateTest(unittest.TestCase):
    def test_first_page(self):
        self.assertEqual(paginate(ITEMS, 1, 2), [1, 2])

    def test_middle_page(self):
        self.assertEqual(paginate(ITEMS, 2, 2), [3, 4])

    def test_paginate_last_page(self):
        self.assertEqual(paginate(ITEMS, 3, 2), [5])

    def test_past_the_end(self):
        self.assertEqual(paginate(ITEMS, 9, 2), [])

    def test_bad_size(self):
        with self.assertRaises(ValueError):
            paginate(ITEMS, 1, 0)


class ValidateTest(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(validate({"price": 1, "quantity": 1}))

    def test_negative_price(self):
        with self.assertRaises(ValueError):
            validate({"price": -1, "quantity": 1})

    def test_zero_price(self):
        self.assertTrue(validate({"price": 0, "quantity": 1}))


if __name__ == "__main__":
    unittest.main()
EOF_F
cat > lint.py <<'EOF_F'
"""Tiny linter: unused imports and lines over 100 chars. Exit 1 on any finding."""
import ast
import pathlib
import sys

findings = []
for path in sorted(pathlib.Path(".").glob("*.py")):
    src = path.read_text()
    for n, line in enumerate(src.splitlines(), 1):
        if len(line) > 100:
            findings.append(f"{path}:{n}: line too long ({len(line)} > 100)")
    tree = ast.parse(src)
    imported = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported[(a.asname or a.name).split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                imported[a.asname or a.name] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.value.id for n in ast.walk(tree)
             if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    for name, lineno in imported.items():
        if name not in used:
            findings.append(f"{path}:{lineno}: unused import {name}")
print("\n".join(findings) if findings else "lint: clean")
sys.exit(1 if findings else 0)
EOF_F
cat > report.py <<'EOF_F'
from orders import calc_total


def summary(orders):
    """One line per order: id and total."""
    return [f"{oid}: {calc_total(items)}" for oid, items in orders]
EOF_F
cat > test_report.py <<'EOF_F'
import unittest

from report import summary


class SummaryTest(unittest.TestCase):
    def test_summary(self):
        self.assertEqual(summary([(1, [(2.5, 2)])]), ["1: 5.00"])
EOF_F
c 2026-09-10 "feat: orders module"
