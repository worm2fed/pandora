---
type: regex
target: {source: file, path: services/api/invoices.py}
---
price = to_gross\(price, customer\["country"\]\)
