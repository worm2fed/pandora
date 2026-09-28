---
type: regex
target: {source: file, path: app/orders.py}
match: not_contains
flags: m
---
^import os\s*$
