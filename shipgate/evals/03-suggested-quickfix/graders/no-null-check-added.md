---
type: regex
target: {source: file, path: app/order_sync.py}
match: not_contains
---
is None|is not None|if not customer|if customer
