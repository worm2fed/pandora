#!/usr/bin/env bash
# Scaffold: builds the synthetic repo in app/ before the agent starts (runs outside the sandbox, --scaffold).
set -e
mkdir app && cd app && git init -q -b main
c() { git add -A && GIT_AUTHOR_DATE="$1T10:00:00+00:00" GIT_COMMITTER_DATE="$1T10:00:00+00:00" git -c user.name=dev -c user.email=dev@example.com -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm "$2"; }
cat > invoices.py <<'PY'
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Invoice:
    number: str
    customer: str
    total: Decimal
    currency: str


def list_invoices():
    return [
        Invoice("INV-001", "Acme", Decimal("200.00"), "USD"),
        Invoice("INV-002", "Globex, Inc.", Decimal("119.00"), "EUR"),
    ]
PY
cat > test_invoices.py <<'PY'
import unittest

from invoices import list_invoices


class ListInvoicesTest(unittest.TestCase):
    def test_lists_two(self):
        self.assertEqual(len(list_invoices()), 2)


if __name__ == "__main__":
    unittest.main()
PY
c 2026-09-10 "feat: invoices module"
