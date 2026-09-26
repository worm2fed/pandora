---
type: regex
target: {source: file, path: app/customers.py}
match: contains
---
return _STORE\.get\(ref\)
