---
type: regex
target: {source: file, path: app/invoice.py}
match: contains
---
price = to_gross\(price, customer\["country"\]\)
